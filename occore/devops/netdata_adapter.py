"""
OZ_A2M 제4부서: 유지보수관리센터 - Netdata 어댑터

실시간 시스템 모니터링 데이터 수집 및 분석
"""

import logging
import threading
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from .models import ResourceMetrics, ServiceStatus, HealthStatus
from .exceptions import HealthCheckError

logger = logging.getLogger(__name__)


class NetdataAdapter:
    """
    Netdata 모니터링 어댑터

    기능:
    - 실시간 시스템 메트릭 수집 (CPU, 메모리, 디스크, 네트워크)
    - 사용자 정의 차트 데이터 (거래 지연, API 응답 시간)
    - 알림 및 이상 징후 감지
    - 히스토리 데이터 조회
    """

    def __init__(self, host: str = "localhost:19999", api_key: Optional[str] = None):
        """
        Netdata 어댑터 초기화

        Args:
            host: Netdata 호스트 (기본: localhost:19999)
            api_key: API 인증 키 (선택적)
        """
        self.host = host
        self.base_url = f"http://{host}/api/v1"
        self.api_key = api_key
        self._connected = False
        self._lock = threading.RLock()

    def connect(self) -> bool:
        """Netdata 연결 확인"""
        try:
            response = requests.get(f"{self.base_url}/info", timeout=5)
            if response.status_code == 200:
                self._connected = True
                logger.info(f"Connected to Netdata: {self.host}")
                return True
        except Exception as e:
            logger.warning(f"Netdata connection failed: {e}")

        self._connected = False
        return False

    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self._connected

    def get_system_metrics(self) -> Dict[str, Any]:
        """
        실시간 시스템 메트릭 조회

        Returns:
            CPU, 메모리, 디스크, 네트워크 메트릭
        """
        if not self._connected:
            raise HealthCheckError("netdata", "Not connected to Netdata")

        metrics = {}

        try:
            # CPU 사용률
            cpu_data = self._get_chart_data("system.cpu", points=1)
            if cpu_data:
                metrics['cpu_percent'] = self._calculate_cpu_usage(cpu_data)

            # 메모리 사용률
            mem_data = self._get_chart_data("system.ram", points=1)
            if mem_data:
                metrics['memory_percent'] = self._calculate_memory_usage(mem_data)

            # 디스크 사용률
            disk_data = self._get_chart_data("disk_usage._", points=1)
            if disk_data:
                metrics['disk_percent'] = disk_data.get('value', 0)

            # 네트워크 지연
            metrics['network_latency_ms'] = self._get_network_latency()

            # 로드 평균
            load_data = self._get_chart_data("system.load", points=1)
            if load_data:
                metrics['load_average'] = load_data.get('value', 0)

            metrics['timestamp'] = datetime.now().isoformat()
            return metrics

        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            raise HealthCheckError("netdata", str(e))

    def get_resource_metrics(self) -> ResourceMetrics:
        """ResourceMetrics 형식으로 변환"""
        metrics = self.get_system_metrics()

        return ResourceMetrics(
            timestamp=datetime.now(),
            cpu_percent=metrics.get('cpu_percent', 0),
            memory_percent=metrics.get('memory_percent', 0),
            memory_used_mb=0,  # Netdata에서 직접 계산 필요
            disk_percent=metrics.get('disk_percent', 0),
            disk_used_gb=0,
            network_latency_ms=metrics.get('network_latency_ms', 0)
        )

    def _get_chart_data(self, chart: str, points: int = 100,
                        after: Optional[int] = None) -> Optional[Dict]:
        """
        Netdata 차트 데이터 조회

        Args:
            chart: 차트 ID (예: system.cpu, system.ram)
            points: 데이터 포인트 수
            after: 현재로부터 몇 초 전 데이터

        Returns:
            차트 데이터
        """
        url = f"{self.base_url}/data"
        params = {"chart": chart, "points": points, "format": "json"}

        if after:
            params["after"] = -after

        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get chart data for {chart}: {e}")
            return None

    def _calculate_cpu_usage(self, data: Dict) -> float:
        """CPU 사용률 계산"""
        if not data or 'data' not in data:
            return 0.0

        try:
            # Netdata CPU 차트는 여러 dimension 제공
            # user, system, nice, iowait, irq, softirq, steal, guest, guest_nice
            latest = data['data'][-1] if data['data'] else None
            if latest and len(latest) > 1:
                # dimension 순서: time, user, system, nice, iowait, irq, softirq, steal, guest
                user = latest[1] if len(latest) > 1 else 0
                system = latest[2] if len(latest) > 2 else 0
                return user + system
        except Exception as e:
            logger.warning(f"CPU calculation error: {e}")

        return 0.0

    def _calculate_memory_usage(self, data: Dict) -> float:
        """메모리 사용률 계산"""
        if not data or 'data' not in data:
            return 0.0

        try:
            latest = data['data'][-1] if data['data'] else None
            if latest and len(latest) > 3:
                # dimension: time, free, used, cached, buffers
                used = latest[2] if len(latest) > 2 else 0
                cached = latest[3] if len(latest) > 3 else 0
                buffers = latest[4] if len(latest) > 4 else 0

                total = sum([used, cached, buffers, latest[1] if len(latest) > 1 else 0])
                if total > 0:
                    return (used / total) * 100
        except Exception as e:
            logger.warning(f"Memory calculation error: {e}")

        return 0.0

    def _get_network_latency(self) -> float:
        """네트워크 지연 시간 측정 (Netdata ping 차트)"""
        try:
            ping_data = self._get_chart_data("netdata.ping", points=1)
            if ping_data and 'data' in ping_data and ping_data['data']:
                latest = ping_data['data'][-1]
                if len(latest) > 1:
                    return latest[1]  # latency value
        except Exception:
            pass

        return 0.0

    def get_alarm_log(self, last_alarms: int = 100) -> List[Dict]:
        """
        Netdata 알림 로그 조회

        Args:
            last_alarms: 최근 알림 수

        Returns:
            알림 목록
        """
        if not self._connected:
            return []

        try:
            url = f"{self.base_url}/alarm_log"
            params = {"after": -last_alarms}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            alarms = response.json()
            return self._parse_alarms(alarms)

        except Exception as e:
            logger.error(f"Failed to get alarm log: {e}")
            return []

    def _parse_alarms(self, alarms: Dict) -> List[Dict]:
        """알림 데이터 파싱"""
        if not alarms or 'alarms' not in alarms:
            return []

        parsed = []
        for alarm in alarms.get('alarms', []):
            parsed.append({
                'id': alarm.get('id'),
                'name': alarm.get('name'),
                'chart': alarm.get('chart'),
                'status': alarm.get('status'),  # CLEAR, WARNING, CRITICAL
                'old_status': alarm.get('old_status'),
                'value': alarm.get('value'),
                'configured': alarm.get('configured'),
                'timestamp': alarm.get('last_updated')
            })

        return parsed

    def get_active_alarms(self) -> List[Dict]:
        """현재 활성화된 알림 조회"""
        alarms = self.get_alarm_log(last_alarms=100)
        return [a for a in alarms if a['status'] in ['WARNING', 'CRITICAL']]

    def check_health(self) -> Tuple[HealthStatus, str]:
        """
        Netdata 기반 헬스 체크

        Returns:
            (HealthStatus, message)
        """
        try:
            metrics = self.get_system_metrics()
            active_alarms = self.get_active_alarms()

            critical_count = sum(1 for a in active_alarms if a['status'] == 'CRITICAL')
            warning_count = sum(1 for a in active_alarms if a['status'] == 'WARNING')

            if critical_count > 0:
                return HealthStatus.CRITICAL, f"{critical_count} critical alarms active"
            elif warning_count > 0:
                return HealthStatus.WARNING, f"{warning_count} warning alarms active"

            return HealthStatus.HEALTHY, "All systems normal"

        except Exception as e:
            return HealthStatus.CRITICAL, f"Health check failed: {e}"

    def get_all_charts(self) -> List[Dict]:
        """사용 가능한 모든 차트 목록"""
        if not self._connected:
            return []

        try:
            response = requests.get(f"{self.base_url}/charts", timeout=10)
            response.raise_for_status()

            data = response.json()
            charts = []

            for chart_id, chart_info in data.get('charts', {}).items():
                charts.append({
                    'id': chart_id,
                    'name': chart_info.get('name'),
                    'title': chart_info.get('title'),
                    'family': chart_info.get('family'),
                    'context': chart_info.get('context'),
                    'units': chart_info.get('units'),
                    'type': chart_info.get('chart_type')
                })

            return charts

        except Exception as e:
            logger.error(f"Failed to get charts: {e}")
            return []

    def get_trading_metrics(self) -> Dict[str, Any]:
        """
        OZ_A2M 트레이딩 관련 메트릭

        Returns:
            사용자 정의 트레이딩 메트릭
        """
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'system': {},
            'network': {},
            'application': {}
        }

        try:
            # 시스템 메트릭
            system_data = self.get_system_metrics()
            metrics['system'] = system_data

            # 네트워크 메트릭
            net_data = self._get_chart_data("system.net", points=1)
            if net_data and 'data' in net_data and net_data['data']:
                latest = net_data['data'][-1]
                metrics['network']['received_kbps'] = latest[1] if len(latest) > 1 else 0
                metrics['network']['sent_kbps'] = latest[2] if len(latest) > 2 else 0

            # TCP 연결 수
            tcp_data = self._get_chart_data("ipv4.tcpsock", points=1)
            if tcp_data and 'data' in tcp_data and tcp_data['data']:
                latest = tcp_data['data'][-1]
                metrics['network']['tcp_connections'] = latest[1] if len(latest) > 1 else 0

            # I/O 대기
            io_data = self._get_chart_data("system.io", points=1)
            if io_data and 'data' in io_data and io_data['data']:
                latest = io_data['data'][-1]
                metrics['system']['io_wait'] = latest[1] if len(latest) > 1 else 0

        except Exception as e:
            logger.error(f"Failed to get trading metrics: {e}")

        return metrics


# 싱글톤 인스턴스
_netdata_adapter_instance: Optional[NetdataAdapter] = None


def get_netdata_adapter(host: str = "localhost:19999",
                        api_key: Optional[str] = None) -> NetdataAdapter:
    """NetdataAdapter 싱글톤 인스턴스 가져오기"""
    global _netdata_adapter_instance
    if _netdata_adapter_instance is None:
        _netdata_adapter_instance = NetdataAdapter(host=host, api_key=api_key)
    return _netdata_adapter_instance


def init_netdata_adapter(host: str = "localhost:19999",
                         api_key: Optional[str] = None) -> NetdataAdapter:
    """NetdataAdapter 초기화 및 연결"""
    global _netdata_adapter_instance
    _netdata_adapter_instance = NetdataAdapter(host=host, api_key=api_key)
    _netdata_adapter_instance.connect()
    return _netdata_adapter_instance

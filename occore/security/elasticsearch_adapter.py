"""
OZ_A2M 제3부서: 보안팀 - Elasticsearch 감사 로그 어댑터

Elasticsearch를 활용한 중앙 집중식 감사 로그 저장 및 검색
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class ElasticsearchAuditAdapter:
    """
    Elasticsearch 감사 로그 어댑터
    
    기능:
    - 실시간 로그 인덱싱
    - 전문 검색 (Full-text search)
    - 집계 및 분석
    - Kibana 연동
    """
    
    def __init__(self, hosts: Optional[List[str]] = None):
        """
        Elasticsearch 어댑터 초기화
        
        Args:
            hosts: Elasticsearch 노드 목록 (기본: localhost:9200)
        """
        self.hosts = hosts or ['localhost:9200']
        self.index_prefix = "oz_a2m_audit"
        self._es = None
        self._connected = False
        
    def connect(self) -> bool:
        """Elasticsearch 연결"""
        try:
            from elasticsearch import Elasticsearch
            self._es = Elasticsearch(self.hosts)
            
            # 연결 확인
            if self._es.ping():
                self._connected = True
                logger.info(f"Connected to Elasticsearch: {self.hosts}")
                self._setup_index_template()
                return True
            else:
                logger.error("Elasticsearch ping failed")
                return False
                
        except ImportError:
            logger.error("elasticsearch package not installed. Run: pip install elasticsearch")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}")
            return False
    
    def _setup_index_template(self):
        """인덱스 템플릿 설정 (매핑 정의)"""
        if not self._connected:
            return
            
        template_name = f"{self.index_prefix}_template"
        
        template = {
            "index_patterns": [f"{self.index_prefix}-*"],
            "settings": {
                "number_of_shards": 1,
                "number_of_replicas": 0,
                "index.lifecycle.name": f"{self.index_prefix}_policy",
                "index.lifecycle.rollover_alias": self.index_prefix
            },
            "mappings": {
                "properties": {
                    "timestamp": {"type": "date"},
                    "event_type": {"type": "keyword"},
                    "user_id": {"type": "keyword"},
                    "ip_address": {"type": "ip"},
                    "command": {"type": "text", "analyzer": "standard"},
                    "details": {"type": "object"},
                    "result": {"type": "keyword"},
                    "risk_score": {"type": "integer"},
                    "session_id": {"type": "keyword"},
                    "severity": {"type": "keyword"},
                    "source": {"type": "keyword"}
                }
            }
        }
        
        try:
            self._es.indices.put_index_template(
                name=template_name,
                body=template
            )
            logger.debug(f"Index template '{template_name}' created")
        except Exception as e:
            logger.warning(f"Index template setup warning: {e}")
    
    def index_log(self, log_entry: Dict[str, Any]) -> Optional[str]:
        """
        로그를 Elasticsearch에 인덱싱
        
        Args:
            log_entry: 로그 항목
            
        Returns:
            문서 ID 또는 None
        """
        if not self._connected:
            logger.warning("Elasticsearch not connected, skipping index")
            return None
            
        try:
            # 일별 인덱스 (로테이션)
            index_name = f"{self.index_prefix}-{datetime.now():%Y.%m.%d}"
            
            # 타임스탬프 처리
            if 'timestamp' not in log_entry:
                log_entry['timestamp'] = datetime.now().isoformat()
            
            response = self._es.index(index=index_name, body=log_entry)
            return response.get('_id')
            
        except Exception as e:
            logger.error(f"Failed to index log: {e}")
            return None
    
    def index_command_log(
        self,
        user_id: Optional[str],
        ip_address: Optional[str],
        command: str,
        details: Optional[Dict] = None,
        result: Optional[str] = None,
        risk_score: int = 0,
        session_id: Optional[str] = None
    ) -> Optional[str]:
        """명령어 로그 인덱싱"""
        log_entry = {
            "event_type": "command",
            "user_id": user_id,
            "ip_address": ip_address,
            "command": command,
            "details": details,
            "result": result,
            "risk_score": risk_score,
            "session_id": session_id,
            "severity": self._risk_to_severity(risk_score),
            "source": "oz_a2m_security"
        }
        return self.index_log(log_entry)
    
    def index_access_attempt(
        self,
        ip_address: str,
        attempt_type: str,
        success: bool,
        user_id: Optional[str] = None,
        reason: Optional[str] = None
    ) -> Optional[str]:
        """접근 시도 로그 인덱싱"""
        log_entry = {
            "event_type": "access_attempt",
            "ip_address": ip_address,
            "attempt_type": attempt_type,
            "success": success,
            "user_id": user_id,
            "reason": reason,
            "severity": "high" if not success else "low",
            "source": "oz_a2m_security"
        }
        return self.index_log(log_entry)
    
    def index_security_alert(
        self,
        alert_type: str,
        severity: str,
        description: str,
        source_ip: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Optional[str]:
        """보안 알림 인덱싱"""
        log_entry = {
            "event_type": "security_alert",
            "alert_type": alert_type,
            "severity": severity,
            "description": description,
            "ip_address": source_ip,
            "user_id": user_id,
            "source": "oz_a2m_security"
        }
        return self.index_log(log_entry)
    
    def search_logs(
        self,
        query: str,
        hours: int = 24,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        """
        로그 검색 (Kibana 스타일 쿼리)
        
        Args:
            query: 검색어 (Lucene 문법 또는 간단한 텍스트)
            hours: 검색할 시간 범위
            event_type: 이벤트 유형 필터
            user_id: 사용자 필터
            limit: 최대 결과 수
            
        Returns:
            검색 결과 목록
        """
        if not self._connected:
            logger.warning("Elasticsearch not connected")
            return []
        
        try:
            # 시간 범위
            time_from = (datetime.now() - timedelta(hours=hours)).isoformat()
            
            # 쿼리 구성
            must_clauses = [
                {"range": {"timestamp": {"gte": time_from}}}
            ]
            
            # 전문 검색
            if query:
                must_clauses.append({
                    "multi_match": {
                        "query": query,
                        "fields": ["command", "details", "description", "user_id"]
                    }
                })
            
            # 필터
            if event_type:
                must_clauses.append({"term": {"event_type": event_type}})
            if user_id:
                must_clauses.append({"term": {"user_id": user_id}})
            
            search_body = {
                "query": {"bool": {"must": must_clauses}},
                "sort": [{"timestamp": {"order": "desc"}}],
                "size": limit
            }
            
            # 인덱스 패턴 (최근 7일)
            indices = [f"{self.index_prefix}-{(datetime.now() - timedelta(days=i)):%Y.%m.%d}" 
                      for i in range(7)]
            index_pattern = ",".join(indices)
            
            response = self._es.search(index=index_pattern, body=search_body)
            
            hits = response.get('hits', {}).get('hits', [])
            return [hit['_source'] for hit in hits]
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def aggregate_by_event_type(self, hours: int = 24) -> Dict[str, int]:
        """이벤트 유형별 집계"""
        if not self._connected:
            return {}
        
        try:
            time_from = (datetime.now() - timedelta(hours=hours)).isoformat()
            
            aggs_body = {
                "query": {"range": {"timestamp": {"gte": time_from}}},
                "size": 0,
                "aggs": {
                    "event_types": {
                        "terms": {"field": "event_type", "size": 20}
                    }
                }
            }
            
            indices = [f"{self.index_prefix}-{(datetime.now() - timedelta(days=i)):%Y.%m.%d}" 
                      for i in range(7)]
            
            response = self._es.search(index=",".join(indices), body=aggs_body)
            
            buckets = response.get('aggregations', {}).get('event_types', {}).get('buckets', [])
            return {bucket['key']: bucket['doc_count'] for bucket in buckets}
            
        except Exception as e:
            logger.error(f"Aggregation failed: {e}")
            return {}
    
    def get_failed_attempts_by_ip(self, hours: int = 24, min_attempts: int = 3) -> List[Dict]:
        """IP별 실패 시도 집계 (브루트 포스 탐지)"""
        if not self._connected:
            return []
        
        try:
            time_from = (datetime.now() - timedelta(hours=hours)).isoformat()
            
            aggs_body = {
                "query": {
                    "bool": {
                        "must": [
                            {"range": {"timestamp": {"gte": time_from}}},
                            {"term": {"success": False}}
                        ]
                    }
                },
                "size": 0,
                "aggs": {
                    "ips": {
                        "terms": {
                            "field": "ip_address",
                            "min_doc_count": min_attempts,
                            "size": 100
                        },
                        "aggs": {
                            "last_attempt": {
                                "max": {"field": "timestamp"}
                            }
                        }
                    }
                }
            }
            
            indices = [f"{self.index_prefix}-{(datetime.now() - timedelta(days=i)):%Y.%m.%d}" 
                      for i in range(7)]
            
            response = self._es.search(index=",".join(indices), body=aggs_body)
            
            buckets = response.get('aggregations', {}).get('ips', {}).get('buckets', [])
            return [
                {
                    "ip": bucket['key'],
                    "count": bucket['doc_count'],
                    "last_attempt": bucket['last_attempt']['value_as_string']
                }
                for bucket in buckets
            ]
            
        except Exception as e:
            logger.error(f"Failed attempts aggregation failed: {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Elasticsearch 인덱스 통계"""
        if not self._connected:
            return {"connected": False}
        
        try:
            # 인덱스 목록
            indices = self._es.indices.get(f"{self.index_prefix}-*")
            
            total_docs = sum(
                idx.get('total', {}).get('docs', {}).get('count', 0)
                for idx in indices.values()
            )
            
            total_size = sum(
                idx.get('total', {}).get('store', {}).get('size_in_bytes', 0)
                for idx in indices.values()
            )
            
            return {
                "connected": True,
                "index_count": len(indices),
                "total_documents": total_docs,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2)
            }
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"connected": True, "error": str(e)}
    
    def _risk_to_severity(self, risk_score: int) -> str:
        """위험 점수를 심각도로 변환"""
        if risk_score >= 80:
            return "critical"
        elif risk_score >= 60:
            return "high"
        elif risk_score >= 40:
            return "medium"
        else:
            return "low"
    
    def is_connected(self) -> bool:
        """연결 상태 확인"""
        return self._connected


# 싱글톤 인스턴스
_es_adapter_instance: Optional[ElasticsearchAuditAdapter] = None


def get_elasticsearch_adapter(hosts: Optional[List[str]] = None) -> ElasticsearchAuditAdapter:
    """ElasticsearchAuditAdapter 싱글톤 인스턴스 가져오기"""
    global _es_adapter_instance
    if _es_adapter_instance is None:
        _es_adapter_instance = ElasticsearchAuditAdapter(hosts=hosts)
    return _es_adapter_instance


def init_elasticsearch_adapter(hosts: Optional[List[str]] = None) -> ElasticsearchAuditAdapter:
    """ElasticsearchAuditAdapter 초기화 및 연결"""
    global _es_adapter_instance
    _es_adapter_instance = ElasticsearchAuditAdapter(hosts=hosts)
    _es_adapter_instance.connect()
    return _es_adapter_instance

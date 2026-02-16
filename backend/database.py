"""
Database layer for AskDiya v2
Persistent storage for audits, results, and historical data
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, ForeignKey, JSON, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

Base = declarative_base()


class Audit(Base):
    """Main audit record"""
    __tablename__ = "audits"
    
    id = Column(String(36), primary_key=True)  # UUID
    college_name = Column(String(500), nullable=False, index=True)
    college_name_normalized = Column(String(500), index=True)
    status = Column(String(50), nullable=False, index=True)  # processing, completed, failed, cancelled
    progress = Column(Integer, default=0)
    progress_message = Column(Text)
    
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime)
    
    time_taken_seconds = Column(Float)
    
    # Summary statistics (stored as JSON)
    summary_json = Column(JSON)
    
    # College metadata
    college_website_url = Column(String(500))
    college_location = Column(String(200))
    
    # Relationships
    results = relationship("AuditResult", back_populates="audit", cascade="all, delete-orphan")
    
    # Indexes for common queries
    __table_args__ = (
        Index('idx_college_created', 'college_name', 'created_at'),
        Index('idx_status_created', 'status', 'created_at'),
    )
    
    def to_dict(self, include_results: bool = True) -> Dict[str, Any]:
        """Convert audit to dictionary"""
        data = {
            "id": self.id,
            "college_name": self.college_name,
            "status": self.status,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "time_taken_seconds": self.time_taken_seconds,
            "summary": self.summary_json,
            "college_website_url": self.college_website_url,
        }
        
        if include_results:
            data["results"] = [r.to_dict() for r in self.results]
        
        return data


class AuditResult(Base):
    """Individual KPI result for an audit"""
    __tablename__ = "audit_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    audit_id = Column(String(36), ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # KPI information
    kpi_name = Column(String(500), nullable=False, index=True)
    category = Column(String(100), index=True)
    value = Column(Text)
    
    # Evidence
    evidence_quote = Column(Text)
    source_url = Column(Text)
    source_type = Column(String(100))
    source_priority = Column(String(50))
    
    # Confidence metrics
    system_confidence = Column(String(20))  # high, medium, low
    confidence_score = Column(Float)  # 0.0 - 1.0
    llm_confidence = Column(String(20))
    llm_confidence_reason = Column(Text)
    
    # Data quality
    data_year = Column(Integer, index=True)
    recency = Column(String(50))
    
    # Validation results (stored as JSON)
    validation_json = Column(JSON)
    quality_scores_json = Column(JSON)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    audit = relationship("Audit", back_populates="results")
    
    # Indexes
    __table_args__ = (
        Index('idx_audit_kpi', 'audit_id', 'kpi_name'),
        Index('idx_kpi_confidence', 'kpi_name', 'system_confidence'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary"""
        return {
            "kpi_name": self.kpi_name,
            "category": self.category,
            "value": self.value,
            "evidence_quote": self.evidence_quote,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_priority": self.source_priority,
            "system_confidence": self.system_confidence,
            "confidence_score": self.confidence_score,
            "llm_confidence": self.llm_confidence,
            "llm_confidence_reason": self.llm_confidence_reason,
            "data_year": self.data_year,
            "recency": self.recency,
            "validation": self.validation_json,
            "quality_scores": self.quality_scores_json,
        }


class RateLimitEntry(Base):
    """Track API usage for rate limiting"""
    __tablename__ = "rate_limits"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    identifier = Column(String(100), nullable=False, index=True)  # IP address or API key
    endpoint = Column(String(200), nullable=False)
    timestamp = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    
    __table_args__ = (
        Index('idx_identifier_timestamp', 'identifier', 'timestamp'),
    )


class DatabaseManager:
    """Manage database connections and operations"""
    
    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize database manager
        
        Args:
            db_url: Database URL (defaults to SQLite in backend folder)
        """
        if db_url is None:
            # Default to SQLite in backend folder
            db_path = Path(__file__).parent / "audits.db"
            db_url = f"sqlite:///{db_path}"
        
        self.engine = create_engine(
            db_url,
            echo=False,  # Set to True for SQL logging
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600,  # Recycle connections after 1 hour
        )
        
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(bind=self.engine)
    
    def get_session(self) -> Session:
        """Get a new database session"""
        return self.SessionLocal()
    
    # ===== Audit Operations =====
    
    def create_audit(
        self,
        audit_id: str,
        college_name: str,
        college_name_normalized: str,
        college_website_url: Optional[str] = None
    ) -> Audit:
        """Create a new audit record"""
        session = self.get_session()
        try:
            audit = Audit(
                id=audit_id,
                college_name=college_name,
                college_name_normalized=college_name_normalized,
                status="processing",
                progress=0,
                progress_message="Starting audit...",
                college_website_url=college_website_url
            )
            session.add(audit)
            session.commit()
            session.refresh(audit)
            return audit
        finally:
            session.close()
    
    def get_audit(self, audit_id: str, include_results: bool = True) -> Optional[Audit]:
        """Get audit by ID"""
        session = self.get_session()
        try:
            audit = session.query(Audit).filter(Audit.id == audit_id).first()
            if audit and include_results:
                # Eagerly load results
                _ = audit.results
            return audit
        finally:
            session.close()
    
    def update_audit_progress(self, audit_id: str, progress: int, message: str):
        """Update audit progress"""
        session = self.get_session()
        try:
            audit = session.query(Audit).filter(Audit.id == audit_id).first()
            if audit:
                audit.progress = progress
                audit.progress_message = message
                audit.updated_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()
    
    def complete_audit(
        self,
        audit_id: str,
        results: List[Dict[str, Any]],
        summary: Dict[str, Any],
        time_taken: float
    ):
        """Mark audit as completed and save results"""
        session = self.get_session()
        try:
            audit = session.query(Audit).filter(Audit.id == audit_id).first()
            if audit:
                audit.status = "completed"
                audit.progress = 100
                audit.progress_message = "Audit complete!"
                audit.completed_at = datetime.now(timezone.utc)
                # Ensure time_taken is float
                audit.time_taken_seconds = float(time_taken) if time_taken else 0.0
                audit.summary_json = summary
                
                # Add results
                for idx, result_data in enumerate(results):
                    try:
                        # Convert data_year to int if it's a string
                        data_year = result_data.get("data_year")
                        if data_year is not None:
                            try:
                                data_year = int(data_year)
                            except (ValueError, TypeError):
                                data_year = None
                        
                        # Convert confidence_score to float if it's a string
                        confidence_score = result_data.get("confidence_score")
                        if confidence_score is not None:
                            try:
                                confidence_score = float(confidence_score)
                            except (ValueError, TypeError):
                                confidence_score = None
                        
                        # Ensure value is converted to string for storage
                        value = result_data.get("value")
                        if value is not None and not isinstance(value, str):
                            value = str(value)
                        
                        result = AuditResult(
                            audit_id=audit_id,
                            kpi_name=result_data.get("kpi_name"),
                            category=result_data.get("category"),
                            value=value,
                            evidence_quote=result_data.get("evidence_quote"),
                            source_url=result_data.get("source_url"),
                            source_type=result_data.get("source_type"),
                            source_priority=result_data.get("source_priority"),
                            system_confidence=result_data.get("system_confidence"),
                            confidence_score=confidence_score,
                            llm_confidence=result_data.get("llm_confidence"),
                            llm_confidence_reason=result_data.get("llm_confidence_reason"),
                            data_year=data_year,
                            recency=result_data.get("recency"),
                            validation_json=result_data.get("validation"),
                            quality_scores_json=result_data.get("quality_scores"),
                        )
                        session.add(result)
                    except Exception as e:
                        logger.error(f"Error adding result {idx} (KPI: {result_data.get('kpi_name')}): {e}")
                        logger.error(f"Result data: {result_data}")
                        raise
                
                session.commit()
        finally:
            session.close()
    
    def fail_audit(self, audit_id: str, error_message: str):
        """Mark audit as failed"""
        session = self.get_session()
        try:
            audit = session.query(Audit).filter(Audit.id == audit_id).first()
            if audit:
                audit.status = "failed"
                audit.progress_message = f"Error: {error_message}"
                audit.completed_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()
    
    def cancel_audit(self, audit_id: str):
        """Mark audit as cancelled"""
        session = self.get_session()
        try:
            audit = session.query(Audit).filter(Audit.id == audit_id).first()
            if audit:
                audit.status = "cancelled"
                audit.progress_message = "Audit cancelled by user"
                audit.completed_at = datetime.now(timezone.utc)
                session.commit()
        finally:
            session.close()
    
    def list_audits(
        self,
        college_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 10,
        offset: int = 0
    ) -> List[Audit]:
        """List audits with optional filtering"""
        session = self.get_session()
        try:
            query = session.query(Audit)
            
            if college_name:
                query = query.filter(Audit.college_name.ilike(f"%{college_name}%"))
            
            if status:
                query = query.filter(Audit.status == status)
            
            query = query.order_by(Audit.created_at.desc())
            query = query.limit(limit).offset(offset)
            
            return query.all()
        finally:
            session.close()
    
    def get_audit_history(self, college_name: str, limit: int = 5) -> List[Audit]:
        """Get audit history for a specific college"""
        session = self.get_session()
        try:
            # Normalize college name for comparison
            from data_parsers import FuzzyMatcher
            normalized = FuzzyMatcher.normalize_college_name(college_name)
            
            audits = session.query(Audit).filter(
                Audit.college_name_normalized == normalized,
                Audit.status == "completed"
            ).order_by(Audit.created_at.desc()).limit(limit).all()
            
            return audits
        finally:
            session.close()
    
    def compare_audits(self, audit_id_1: str, audit_id_2: str) -> Dict[str, Any]:
        """Compare two audits and return differences"""
        session = self.get_session()
        try:
            audit1 = session.query(Audit).filter(Audit.id == audit_id_1).first()
            audit2 = session.query(Audit).filter(Audit.id == audit_id_2).first()
            
            if not audit1 or not audit2:
                return {"error": "One or both audits not found"}
            
            # Build KPI maps
            kpis1 = {r.kpi_name: r for r in audit1.results}
            kpis2 = {r.kpi_name: r for r in audit2.results}
            
            comparison = {
                "audit_1": {
                    "id": audit1.id,
                    "date": audit1.created_at.isoformat() if audit1.created_at else None,
                    "summary": audit1.summary_json
                },
                "audit_2": {
                    "id": audit2.id,
                    "date": audit2.created_at.isoformat() if audit2.created_at else None,
                    "summary": audit2.summary_json
                },
                "changes": []
            }
            
            # Find changes
            all_kpis = set(kpis1.keys()) | set(kpis2.keys())
            
            for kpi_name in all_kpis:
                r1 = kpis1.get(kpi_name)
                r2 = kpis2.get(kpi_name)
                
                if not r1:
                    comparison["changes"].append({
                        "kpi": kpi_name,
                        "change_type": "added",
                        "old_value": None,
                        "new_value": r2.value if r2 else None
                    })
                elif not r2:
                    comparison["changes"].append({
                        "kpi": kpi_name,
                        "change_type": "removed",
                        "old_value": r1.value if r1 else None,
                        "new_value": None
                    })
                elif r1.value != r2.value:
                    comparison["changes"].append({
                        "kpi": kpi_name,
                        "change_type": "modified",
                        "old_value": r1.value if r1 else None,
                        "new_value": r2.value if r2 else None,
                        "old_confidence": r1.system_confidence,
                        "new_confidence": r2.system_confidence
                    })
            
            return comparison
        finally:
            session.close()
    
    # ===== Rate Limiting Operations =====
    
    def check_rate_limit(
        self,
        identifier: str,
        endpoint: str,
        max_requests: int = 10,
        window_seconds: int = 60
    ) -> tuple[bool, int]:
        """
        Check if request is within rate limit
        
        Returns:
            (is_allowed, requests_remaining)
        """
        session = self.get_session()
        try:
            from datetime import timedelta
            
            cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
            
            # Count requests in window
            count = session.query(RateLimitEntry).filter(
                RateLimitEntry.identifier == identifier,
                RateLimitEntry.endpoint == endpoint,
                RateLimitEntry.timestamp >= cutoff_time
            ).count()
            
            is_allowed = count < max_requests
            remaining = max(0, max_requests - count)
            
            if is_allowed:
                # Record this request
                entry = RateLimitEntry(
                    identifier=identifier,
                    endpoint=endpoint,
                    timestamp=datetime.now(timezone.utc)
                )
                session.add(entry)
                session.commit()
                remaining -= 1
            
            return is_allowed, remaining
        finally:
            session.close()
    
    def cleanup_old_rate_limits(self, hours: int = 24):
        """Clean up old rate limit entries"""
        session = self.get_session()
        try:
            from datetime import timedelta
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
            
            session.query(RateLimitEntry).filter(
                RateLimitEntry.timestamp < cutoff_time
            ).delete()
            
            session.commit()
        finally:
            session.close()
    
    # ===== Cleanup Operations =====
    
    def delete_old_audits(self, days: int = 30, keep_completed: bool = True):
        """Delete old audits to save space"""
        session = self.get_session()
        try:
            from datetime import timedelta
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
            
            query = session.query(Audit).filter(Audit.created_at < cutoff_time)
            
            if keep_completed:
                query = query.filter(Audit.status != "completed")
            
            deleted = query.delete()
            session.commit()
            
            return deleted
        finally:
            session.close()


# Global database manager instance
db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get or create the global database manager"""
    global db_manager
    if db_manager is None:
        # Check for DATABASE_URL environment variable
        db_url = os.getenv("DATABASE_URL")
        db_manager = DatabaseManager(db_url)
    return db_manager


def init_database(db_url: Optional[str] = None):
    """Initialize the database"""
    global db_manager
    db_manager = DatabaseManager(db_url)
    return db_manager

"""
Enhanced Error Handling & Retry Logic with Circuit Breaker
===========================================================
Implements robust error handling, exponential backoff, circuit breaker, and graceful degradation.
"""

import time
import logging
import functools
import asyncio
from typing import Optional, Callable, Any, Dict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states"""
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern to prevent repeated calls to failing services.
    Automatically opens after failure_threshold failures, then tests recovery.
    """
    failure_threshold: int = 5
    timeout_duration: int = 60  # seconds
    half_open_max_calls: int = 3
    
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: Optional[datetime] = field(default=None, init=False)
    _half_open_calls: int = field(default=0, init=False)
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function through circuit breaker"""
        if self._state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"Circuit breaker entering HALF_OPEN state for {func.__name__}")
            else:
                raise Exception(f"Circuit breaker OPEN for {func.__name__}. Try again later.")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self._last_failure_time is None:
            return False
        return datetime.now() - self._last_failure_time > timedelta(seconds=self.timeout_duration)
    
    def _on_success(self):
        """Handle successful call"""
        if self._state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker CLOSED - service recovered")
        else:
            self._failure_count = 0
    
    def _on_failure(self):
        """Handle failed call"""
        self._failure_count += 1
        self._last_failure_time = datetime.now()
        
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("Circuit breaker reopened - service still failing")
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(f"Circuit breaker OPEN after {self._failure_count} failures")
    
    def reset(self):
        """Manually reset circuit breaker"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        logger.info("Circuit breaker manually reset")


def exponential_backoff_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 32.0,
    exponential_base: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for exponential backoff retry logic.
    
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        exponential_base: Base for exponential calculation
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func):
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(f"{func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
            
            raise last_exception
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(f"{func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    delay = min(base_delay * (exponential_base ** attempt), max_delay)
                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    await asyncio.sleep(delay)
            
            raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def graceful_degradation(fallback_value: Any = None, log_failure: bool = True):
    """
    Decorator for graceful degradation - return fallback value on failure.
    
    Args:
        fallback_value: Value to return if function fails
        log_failure: Whether to log the failure
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_failure:
                    logger.warning(f"{func.__name__} failed, using fallback: {e}")
                return fallback_value
        return wrapper
    return decorator


class APIKeyRotator:
    """
    Rotates through multiple API keys when one is exhausted.
    Implements intelligent rotation with failure tracking.
    """
    def __init__(self, api_keys: list, cooldown_period: int = 300):
        """
        Args:
            api_keys: List of API keys to rotate through
            cooldown_period: Seconds to wait before retrying a failed key
        """
        self.api_keys = api_keys if isinstance(api_keys, list) else [api_keys]
        self.current_index = 0
        self.cooldown_period = cooldown_period
        self.failed_keys: Dict[str, datetime] = {}
        self.exhausted_keys: set = set()
    
    def get_current_key(self) -> Optional[str]:
        """Get currently active API key"""
        if not self.api_keys:
            return None
        
        # Try to find a non-failed, non-exhausted key
        attempts = 0
        while attempts < len(self.api_keys):
            key = self.api_keys[self.current_index]
            
            # Skip exhausted keys
            if key in self.exhausted_keys:
                self._rotate()
                attempts += 1
                continue
            
            # Check if key is in cooldown
            if key in self.failed_keys:
                time_since_failure = (datetime.now() - self.failed_keys[key]).total_seconds()
                if time_since_failure < self.cooldown_period:
                    self._rotate()
                    attempts += 1
                    continue
                else:
                    # Cooldown expired, remove from failed keys
                    del self.failed_keys[key]
            
            return key
        
        # All keys are either exhausted or in cooldown
        logger.error("All API keys are exhausted or in cooldown")
        return None
    
    def mark_key_failed(self, key: str, exhausted: bool = False):
        """Mark a key as failed or exhausted"""
        if exhausted:
            self.exhausted_keys.add(key)
            logger.error(f"API key exhausted (permanently): ...{key[-6:] if len(key) >= 6 else 'XXX'}")
        else:
            self.failed_keys[key] = datetime.now()
            logger.warning(f"API key failed (temporary cooldown): ...{key[-6:] if len(key) >= 6 else 'XXX'}")
        
        self._rotate()
    
    def _rotate(self):
        """Rotate to next key"""
        self.current_index = (self.current_index + 1) % len(self.api_keys)
    
    def has_available_keys(self) -> bool:
        """Check if any keys are still available"""
        return len(self.exhausted_keys) < len(self.api_keys)
    
    def reset_cooldowns(self):
        """Reset all cooldown timers (use sparingly)"""
        self.failed_keys.clear()
        logger.info("All API key cooldowns reset")


# Global circuit breakers for different services
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str, **kwargs) -> CircuitBreaker:
    """Get or create circuit breaker for a service"""
    if service_name not in _circuit_breakers:
        _circuit_breakers[service_name] = CircuitBreaker(**kwargs)
    return _circuit_breakers[service_name]


def with_circuit_breaker(service_name: str):
    """Decorator to wrap function with circuit breaker"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            breaker = get_circuit_breaker(service_name)
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator

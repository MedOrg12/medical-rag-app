"""
Simple metrics tracking and logging for monitoring pipeline performance.
"""

import time
from contextlib import contextmanager
from typing import Any

from src.logging_config import get_logger

logger = get_logger()


class MetricsTracker:
    """Track and log key performance metrics."""

    def __init__(self) -> None:
        """Initialize metrics tracker."""
        self.metrics: dict[str, Any] = {}
        self.timers: dict[str, float] = {}

    def record(self, metric_name: str, value: Any) -> None:
        """
        Record a metric value.

        Args:
            metric_name: Name of the metric
            value: Value to record
        """
        self.metrics[metric_name] = value

    def increment(self, metric_name: str, amount: int = 1) -> None:
        """
        Increment a counter metric.

        Args:
            metric_name: Name of the counter
            amount: Amount to increment by
        """
        current = self.metrics.get(metric_name, 0)
        self.metrics[metric_name] = current + amount

    def start_timer(self, timer_name: str) -> None:
        """
        Start a timer.

        Args:
            timer_name: Name of the timer
        """
        self.timers[timer_name] = time.time()

    def stop_timer(self, timer_name: str) -> float:
        """
        Stop a timer and return elapsed time.

        Args:
            timer_name: Name of the timer

        Returns:
            Elapsed time in seconds
        """
        if timer_name not in self.timers:
            logger.warning(f"Timer '{timer_name}' was never started")
            return 0.0

        elapsed = time.time() - self.timers[timer_name]
        del self.timers[timer_name]
        self.record(f"{timer_name}_seconds", elapsed)
        return elapsed

    @contextmanager
    def timer(self, timer_name: str):
        """
        Context manager for timing code blocks.

        Args:
            timer_name: Name of the timer

        Example:
            with metrics.timer("pdf_parsing"):
                parse_pdf(file)
        """
        self.start_timer(timer_name)
        try:
            yield
        finally:
            elapsed = self.stop_timer(timer_name)
            logger.debug(f"Timer '{timer_name}': {elapsed:.2f}s")

    def get_metric(self, metric_name: str) -> Any | None:
        """
        Get a metric value.

        Args:
            metric_name: Name of the metric

        Returns:
            Metric value or None if not found
        """
        return self.metrics.get(metric_name)

    def get_all_metrics(self) -> dict[str, Any]:
        """
        Get all recorded metrics.

        Returns:
            Dictionary of all metrics
        """
        return self.metrics.copy()

    def log_summary(self, title: str = "Metrics Summary") -> None:
        """
        Log a summary of all metrics.

        Args:
            title: Title for the summary
        """
        if not self.metrics:
            logger.info(f"{title}: No metrics recorded")
            return

        logger.info(f"\n{'='*80}")
        logger.info(title)
        logger.info("=" * 80)

        # Group metrics by category
        timers = {k: v for k, v in self.metrics.items() if k.endswith("_seconds")}
        counters = {k: v for k, v in self.metrics.items() if isinstance(v, int)}
        rates = {
            k: v for k, v in self.metrics.items() if k.endswith("_rate") or k.endswith("_percent")
        }
        other = {
            k: v
            for k, v in self.metrics.items()
            if k not in timers and k not in counters and k not in rates
        }

        if timers:
            logger.info("\nTiming:")
            for name, value in timers.items():
                display_name = name.replace("_seconds", "")
                logger.info(f"  {display_name}: {value:.2f}s")

        if counters:
            logger.info("\nCounts:")
            for name, value in counters.items():
                logger.info(f"  {name}: {value}")

        if rates:
            logger.info("\nRates:")
            for name, value in rates.items():
                if isinstance(value, float):
                    logger.info(f"  {name}: {value:.1f}%")
                else:
                    logger.info(f"  {name}: {value}")

        if other:
            logger.info("\nOther:")
            for name, value in other.items():
                logger.info(f"  {name}: {value}")

        logger.info("=" * 80 + "\n")

    def clear(self) -> None:
        """Clear all metrics and timers."""
        self.metrics.clear()
        self.timers.clear()


# Global metrics instance for convenience
_global_metrics = MetricsTracker()


def get_metrics() -> MetricsTracker:
    """
    Get the global metrics tracker instance.

    Returns:
        Global MetricsTracker instance
    """
    return _global_metrics

"""Run durable shop forecast tickets outside the day-close browser request."""

import logging
from threading import Event, Thread

from app.shop_forecast import build_shop_forecasts


LOG = logging.getLogger(__name__)


class ForecastWorker:
    def __init__(self, shop, *, builder=build_shop_forecasts):
        self.shop = shop
        self.builder = builder
        self._stop = Event()
        self._thread = None

    def run_once(self):
        """Claim one ticket; useful for both the worker loop and deterministic tests."""
        job = self.shop.claim_forecast_job()
        if job is None:
            return False
        day, version = job["origin_day"], job["origin_version"]
        LOG.info("Forecast task started: day=%s version=%s", day, version)
        try:
            results = self.builder(self.shop, day)
            self.shop.save_forecast_results(day, version, results, complete_job=True)
        except Exception as error:
            if self.shop.fail_forecast_job(day, version, error):
                LOG.exception("Forecast task failed: day=%s version=%s", day, version)
            else:
                LOG.info("Forecast task was cancelled: day=%s version=%s", day, version)
        else:
            LOG.info("Forecast task completed: day=%s version=%s products=%s", day, version, len(results))
        return True

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.run_once():
                    continue
            except Exception:
                LOG.exception("Forecast worker could not claim a task")
            self._stop.wait(1)

    def start(self):
        self.shop.recover_forecast_jobs()
        self._thread = Thread(target=self._run, name="forecast-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def is_alive(self):
        return self._thread is not None and self._thread.is_alive()

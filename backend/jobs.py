import queue
import threading

import config


class Job:
    def __init__(self, video_id, lang):
        self.video_id = video_id
        self.lang = lang
        self.key = config.cache_key(video_id, lang)
        self.queue = queue.Queue()
        self.status = "pending"   # pending | running | done | error
        self.error = None
        self.thread = None

    def emit(self, stage, percent, message=""):
        self.queue.put({"stage": stage, "percent": percent, "message": message})

    def finish(self, status, error=None):
        self.status = status
        self.error = error
        self.queue.put({"status": status, "error": error})


_jobs = {}
_lock = threading.Lock()


def get_or_create(video_id, lang):
    key = config.cache_key(video_id, lang)
    with _lock:
        job = _jobs.get(key)
        if job and job.status in ("pending", "running"):
            return job, False
        job = Job(video_id, lang)
        _jobs[key] = job
        return job, True


def get(video_id, lang):
    return _jobs.get(config.cache_key(video_id, lang))

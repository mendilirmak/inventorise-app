# Two stages: "build" installs the Python packages into a virtual env,
# the final stage copies only that venv and the app code. Build tools and
# pip caches never reach the image that runs in production.

# Exact tag (Python 3.12.15 on Debian trixie) so every build uses the same base.
FROM python:3.12.15-slim-trixie AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/pip install -r requirements.txt


FROM python:3.12.15-slim-trixie

# PYTHONDONTWRITEBYTECODE: no .pyc files (the root filesystem is read-only
# in Kubernetes). PYTHONUNBUFFERED: logs appear immediately.
# FLASK_APP: lets `flask create-user` find the app.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app

# Run as an unprivileged user, never as root.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY app/ app/

USER 10001
EXPOSE 8000

# Docker marks the container unhealthy if /health/live stops answering.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

# One worker process with 4 threads per container: Kubernetes adds more
# containers (HPA) when more capacity is needed. --worker-tmp-dir uses
# memory instead of disk, so a read-only root filesystem works.
# --access-logfile is off because the app writes its own JSON request log.
# --no-control-socket: gunicorn's admin socket is not used, and it would try
# to write into $HOME on the read-only filesystem.
ENTRYPOINT ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", \
            "--worker-tmp-dir", "/dev/shm", "--access-logfile", "/dev/null", \
            "--no-control-socket"]
CMD ["app:create_app()"]

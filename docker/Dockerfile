FROM python:3.12-slim-bookworm

RUN python -m pip install --no-cache-dir \
    mypy==1.20.2 \
    pytest==8.4.2 \
    ruff==0.16.0

ENV HOME=/tmp/home \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/tmp \
    XDG_CACHE_HOME=/tmp/cache

WORKDIR /workspace
USER 65532:65532
ENTRYPOINT []
CMD ["pytest", "--version"]

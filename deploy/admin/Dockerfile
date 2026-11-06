# Python/라이브러리 환경을 모든 팀원 PC에서 통일
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 패키지는 이미지 빌드 때만 설치 (Windows Python/Conda 불필요)
COPY deploy/admin/requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

# 기존 6개 모듈을 그대로 사용
COPY database/ /app/database/

EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "database/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENTRYPOINT ["robot-simulator"]
CMD ["--count", "20", "--interval", "0.5"]

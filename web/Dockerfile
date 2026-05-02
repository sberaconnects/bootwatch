# web/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    linux-perf \
    perl \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download flamegraph.pl at build time
RUN mkdir -p /opt/flamegraph && \
    curl -fsSL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/flamegraph.pl \
         -o /opt/flamegraph/flamegraph.pl && \
    chmod +x /opt/flamegraph/flamegraph.pl && \
    curl -fsSL https://raw.githubusercontent.com/brendangregg/FlameGraph/master/stackcollapse-perf.pl \
         -o /opt/flamegraph/stackcollapse-perf.pl && \
    chmod +x /opt/flamegraph/stackcollapse-perf.pl

COPY . .

ENV FLAMEGRAPH_BIN=/opt/flamegraph/flamegraph.pl
ENV STACKCOLLAPSE_BIN=/opt/flamegraph/stackcollapse-perf.pl

EXPOSE 5000
CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]

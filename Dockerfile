# FinTel Docker image for scheduler / agents (Phase 4+)
#
# Build with:
#   docker build -t fintel:latest .
# Run with:
#   docker run -d --name fintel-scheduler fintel:latest
#   (or mount workspace to edit code)

FROM python:3.14-slim

# avoid prompts and reduce layers
ENV DEBIAN_FRONTEND=noninteractive

# create non-root user for nicer permissions
RUN useradd -m -u 1000 fintel
WORKDIR /home/fintel/app

# copy requirements first for caching
COPY requirements.txt /home/fintel/app/
RUN pip install --no-cache-dir -r requirements.txt

# copy project
COPY . /home/fintel/app/
RUN chown -R fintel:fintel /home/fintel/app

USER fintel

# default command runs scheduler continuously; override to run other modules
CMD ["python", "-m", "agents.scheduler"]

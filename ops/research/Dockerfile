FROM python:3.11-slim-bookworm
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir numpy scipy pandas matplotlib scikit-learn sympy networkx
WORKDIR /research
ENV MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
CMD ["python", "--version"]

FROM python:3.11-slim
RUN pip install --no-cache-dir numpy scipy pandas matplotlib scikit-learn sympy networkx
WORKDIR /research
ENV MPLCONFIGDIR=/tmp/matplotlib PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
CMD ["python", "--version"]

FROM python:3.12-alpine

RUN rm -rf /var/cache/apk/*

#install python dependencies from requirements.txt
COPY requirements.txt /opt/redalert/
RUN pip install -r /opt/redalert/requirements.txt --no-cache-dir

ENV PYTHONIOENCODING=utf-8

ENV LANG=C.UTF-8

COPY redalert.py /opt/redalert

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:8080/health || exit 1

ENTRYPOINT ["python", "/opt/redalert/redalert.py"]
